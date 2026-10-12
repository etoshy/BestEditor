# 14 · Direções (predefinições)

Uma **Direção** aplica tudo de uma vez num vídeo: templates, transições, movimento, filtro, entradas e saídas,
overlays, destaques, cores e legenda.

- Cada eixo tem uma **%** (de trechos, emendas ou regiões) e itens com **peso**.
- A mesma **semente** gera a mesma edição, e cada clique sorteia outra.

De fábrica são quatro: Padrão do sistema, Documentário clássico, Cinema premium e Cortes dinâmicos. Ficam em
`darkplanner.json → presets.system`.

## Sem programar (o jeito certo)

No Estúdio: 🎨 Direção → **＋ Nova**, **⧉ Duplicar** uma do sistema ou **✎ Editar** uma sua. O editor tem:

| Eixo | O que você marca |
|---|---|
| Templates, Transições, Movimento, Filtros, Animações (entrada), Saídas, Overlays | os itens (galeria com prévia, busca, "✓ Do meu kit") e o **peso** de cada um, mais a **%** do eixo |
| Destaques | a densidade (minimal, equilibrado, dinâmico, máximo) e os estilos permitidos (vazio = o kit do projeto) |
| Editoriais | se usa os 🗞 quadros editoriais, a densidade (1 quadro a cada ~60 s, 40 s, 25 s ou 15 s) e os tipos que a IA pode usar (vazio = todos) |
| Legenda | o estilo que vem junto (leva a config da aba Legendas) |
| Cor | cor original de cada destaque / cor da predefinição / cor do projeto |
| Ritmo e Universo | calmo → muito dinâmico; *estrita* (só o que marcou) ou *catálogo inteiro onde eu não marcar* |

**Tudo o que você criou nos extras** (transições, efeitos, entradas, filtros, destaques, cenas) aparece nessas
galerias e pode ganhar peso numa Direção sua.

### Extras que entram sozinhos nas Direções do sistema

Um item de extra com `"direcoes": ["sys_cinema", "sys_doc_classico"]` entra nessas Direções de fábrica, sem você
editar nada:

- transições, filtros, entradas e efeitos/overlays entram com peso 1. Os itens que a Direção já tinha ganham peso
  maior, para continuarem com **pelo menos metade** das escolhas;
- se a Direção não usava animações de entrada (0%), ela passa a usar 15% quando ganha entradas dos extras;
- cenas entram na lista de templates, mas a % de templates não muda (as de referência vêm com `autoEligible: false`);
- no **Padrão do sistema** nada muda, porque ele já usa o catálogo inteiro (que já tem todos os extras);
- destaques e paletas não mudam a Direção: as de fábrica já deixam todos os estilos e paletas disponíveis.

O resumo da Direção (aba 🎨 Direção) mostra quantos itens vieram dos extras. Para mexer nos pesos, use **⧉ Duplicar**.

As suas Direções ficam em `predefinicoes_usuario.json`, na pasta do site. Para levar para outro PC, copie esse
arquivo. A IA do prompt de edição também pode escolher uma Direção sua pelo id.

**★ Minha direção**: o que você marca com "✓ Marcar kit" nas galerias (Biblioteca, Destaques, Transições) vira essa
direção automaticamente.

## Com código

- `dp_direcao.planejar()`: o plano (regras físicas: câmera só em foto, um filtro por vídeo, template precisa de N
  trechos livres e respeita o intervalo mínimo).
- `EIXOS`, `RITMOS`, `DENSIDADES`: os valores aceitos.
- `normalizar_predefinicao()`: o formato salvo.

## Direções tiradas de canais de referência

`direcoes_canais.py` guarda direções montadas a partir da análise de um vídeo de um criador (cortes, quadros, textos e
áudio), traduzidas para os itens que o site já tem. Elas aparecem na lista junto com as do sistema. Um id que não existir
na instalação (por exemplo, sem o pacote de extras) é ignorado, e a direção segue com o resto.

- **Rabbit hole sombrio (estilo Mistere)** (`sys_mistere`): cortes de ~3 s, filtro frio com vinheta, estática e glitch de
  TV nas viradas, números gigantes e máquina de escrever, sem legenda queimada. O modelo de vídeo "🕳 Rabbit holes
  bizarros" aplica essa direção sozinho.
