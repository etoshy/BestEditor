# 📘 Guia — como criar efeitos, transições, destaques, textos, legendas e tudo do DarkPlanner

Este guia explica **como criar coisas novas** no editor (o Estúdio): transições, efeitos, entradas e saídas,
filtros, destaques de texto, textos animados, legendas, fundos, cenas e takes, gráficos, sons, fontes, paletas,
direções, a biblioteca de miniaturas e a censura.

Ele também aparece dentro do site: rodapé → **📘 Guia** (endereço `/guia`). A página mostra os seus extras e os
erros que eles tiverem.

## Os dois jeitos de criar

| Jeito | Quando usar | Onde |
|---|---|---|
| **➕ Extras (sem programar)** | Uma variação do que já existe: outra transição nativa do ffmpeg, uma fórmula própria, um filtro de cor, um efeito de cor/brilho, uma entrada com outra duração, um destaque que copia outro e muda fonte/cores/animação/fundo/som, uma cena com janelas próprias, uma paleta, um som, uma fonte | Um arquivo `.json` em `assets/darkplanner/extras/` |
| **🛠 Código** | Um visual que não existe em nenhum lugar: uma forma nova de destaque, um estilo de legenda novo, um fundo desenhado novo, um tipo de gráfico novo, uma textura animada nova | Os arquivos `dp_*.py` + a prévia em `templates/estudio.html` |

Os extras ficam numa pasta só sua. Atualizar o site (extrair um zip novo por cima) **não apaga** eles.
Se você usa GitHub, eles sobem junto com o resto.

## Passo a passo com extras

1. Copie um exemplo de [exemplos/](exemplos/destaques.json) para `assets/darkplanner/extras/`.
   Pode ser um arquivo por tipo ou tudo num arquivo só. Arquivo que começa com `_` é ignorado.
2. Mude o `id`, o `rotulo` e o que quiser.
3. Rode `python dp_guia.py verificar`. Ele mostra erro de digitação, id repetido, base que não existe, fonte ou som
   que não existe…
4. Rode `python dp_guia.py miniaturas`. Ele gera **só** as miniaturas que faltam: a imagem do destaque, a foto com o
   filtro, a animação da entrada, a prévia do overlay.
5. Reinicie o site (`python app.py`). Ou, no 📘 Guia, clique em **🔄 Reler os extras**.
   **Transição nova só passa a valer depois de reiniciar.**

O que você criou aparece em todos os lugares, como os itens de fábrica:

- nas galerias do Estúdio (com busca e "✓ Marcar kit");
- no **prompt de edição da IA**, que pode escolher o item pelo id;
- no editor de **Direções** (predefinições);
- na **montagem** (ffmpeg).

## Os capítulos

| # | Assunto | Sem programar? |
|---|---|---|
| [01](01-transicoes.md) | Transições | ✅ `xfade`, fórmula `expr` ou `igual_a` |
| [02](02-efeitos-e-overlays.md) | Efeitos de câmera e de atmosfera (overlays) | ✅ câmera, cadeia de filtros, `igual_a` |
| [03](03-entradas-e-saidas.md) | Entradas e saídas dos trechos | ✅ gesto existente com outra duração |
| [04](04-filtros.md) | Filtros de cor | ✅ cadeia do ffmpeg + CSS da prévia |
| [05](05-destaques.md) | Destaques de texto (os 207 estilos) | ✅ `base` + o que muda |
| [06](06-textos-animados.md) | Textos animados avulsos (aba 🔤 Textos e página /textos) | ✅ usa os destaques |
| [07](07-legendas.md) | Legendas (bloco e karaokê) | 🛠 código (as opções já mudam bastante) |
| [08](08-fundos.md) | Fundos dos destaques e das cenas | parcial: usar sim, fundo novo é código |
| [09](09-cenas-e-takes.md) | Cenas e takes (templates com janelas) | ✅ `base`, `arranjo` ou `janelas` |
| [10](10-graficos.md) | Gráficos animados | 🛠 código (o estilo muda pelas cores) |
| [11](11-sons.md) | Sons (efeitos sonoros) | ✅ `python dp_guia.py som` |
| [12](12-fontes.md) | Fontes | ✅ `python dp_guia.py fonte` |
| [13](13-cores-e-paletas.md) | Cores e paletas | ✅ seção `paletas` (ou pelo próprio Estúdio) |
| [14](14-direcoes.md) | Direções / predefinições | ✅ pelo próprio Estúdio |
| [15](15-biblioteca-e-galeria.md) | Biblioteca do Estúdio, miniaturas e kit | ✅ `python dp_guia.py miniaturas` |
| [16](16-censura.md) | Censura (blur, pixelado, tarja, bip) | 🛠 código |
| [17](17-ferramentas-e-testes.md) | `dp_guia.py`, testes e o checklist de código | — |
| [18](18-quadros-editoriais.md) | 🗞 Quadros editoriais (ficha, post, terminal, recortes, mural, número…) | ✅ pelo Estúdio; tipo novo é código |
| [19](19-ia-nas-buscas-e-modelos.md) | 🤖 IA nas buscas, no editor e nos Modelos de vídeo (Claude Haiku 5.5) + prompt de edição em partes | ✅ página 🤖 IA |

## Mapa dos arquivos

| Arquivo | O que tem |
|---|---|
| `assets/darkplanner/darkplanner.json` | O catálogo do DarkPlanner: transições, efeitos, entradas, filtros, os 207 destaques, regras, direções |
| `assets/darkplanner/cenas_catalogo.json` | Os 149 templates de cena/take |
| `assets/darkplanner/extras/*.json` | **Os seus extras** (ver `dp_extras.py`) |
| `assets/darkplanner/galeria/` | Miniaturas e prévias das galerias |
| `assets/sons/` + `sons.json` | Os efeitos sonoros (com o instante do pico de cada um) |
| `assets/fonts/dp/` + `fontes.json` | As fontes (família interna "DP …") |
| `dp_visual.py` | Filtros, efeitos, entradas/saídas e transições → ffmpeg |
| `dp_destaques.py` | Destaques de texto → legenda ASS animada (libass) + tratamento da cena |
| `dp_legendas.py` | Legendas (bloco e karaokê) |
| `dp_fundos.py` | Fundos dos destaques e das cenas |
| `cenas_dp.py` | Cenas/takes (arranjos de janelas) e os shutters |
| `dp_graficos.py` | Gráficos animados (PIL → .mov com transparência) |
| `dp_sons.py` | Sons: manifesto, som automático das transições, mixagem |
| `dp_cores.py` | Paleta do projeto e tons |
| `dp_direcao.py` | Direções (predefinições) e o plano automático |
| `dp_censura.py` | Censura de imagem e áudio |
| `dp_galeria.py` | Gera as miniaturas e prévias |
| `dp_extras.py` / `dp_guia.py` | Os extras e as ferramentas deste guia |
| `templates/estudio.html` | O Estúdio: galerias e a **prévia** no monitor (CSS/JS) |
| `prompt_edicao.py` | O prompt de edição da IA (lista o catálogo, já com os extras) |

## A regra de ouro: prévia = vídeo exportado

Tudo no Estúdio é desenhado **duas vezes**:

- uma vez no navegador, para a prévia no monitor (CSS/JS em `estudio.html`);
- outra vez no ffmpeg, para o vídeo final (os `dp_*.py`).

Nos extras, a prévia se vira sozinha:

- uma transição `xfade` usa a prévia da nativa;
- uma entrada `igual_a` usa a prévia do gesto;
- um filtro usa o seu `css`;
- um destaque usa o mesmo desenho do estilo base.

No código, **sempre mexa nos dois lados** (o capítulo [17](17-ferramentas-e-testes.md) tem o checklist).
