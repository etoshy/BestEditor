# 10 · Gráficos animados

Faixa **Gráficos** da timeline (📊 Gráfico no cursor, ou duplo clique na faixa). A IA também cria gráficos pelo
prompt de edição.

| Tipo | Animação |
|---|---|
| `barras` | barras crescendo |
| `barras_h` | barras deitadas |
| `linha` | a linha se desenha |
| `pizza` / `rosca` | as fatias giram |
| `comparacao` | A × B |
| `numero` | o número grande conta |
| `progresso` | porcentagem num anel |

## Sem programar

Sem programar, mude o **visual** no painel 🎨 Cores do gráfico:

- esquema: tons da paleta, uma cor só, monocromático, cores vivas ou uma cor por item;
- cartão: escuro, claro ou sem cartão;
- cor principal, cor dos itens fora do destaque, cor e opacidade do fundo, cor do texto;
- cor de cada item, também pelos dados: `rótulo: valor #RRGGBB`.

Posições: centro, esquerda, direita, embaixo e tela cheia.

## Com código: tipo novo

Em `dp_graficos.py`:

1. `TIPOS["meu_tipo"] = "Nome"`. Ele aparece sozinho no seletor do Estúdio e na lista da IA.
2. Em `normalizar()`, diga quantos itens no mínimo o tipo precisa (`minimo`).
3. Em `desenhar(g, t, W, H, primaria)`, acrescente o `elif tipo == "meu_tipo":` que desenha **um quadro** no
   instante `t`. Use:
   - `_ease()` para suavizar;
   - `ENTRADA_S` (duração da entrada);
   - `caixa()` (o retângulo do gráfico);
   - `_cores()` (as cores do esquema);
   - `formatar()` (número + unidade).
4. A prévia do Estúdio é o último quadro, feito pelo próprio `previa_png()`. Não precisa de JS.
5. `pytest test_v76_ia_graficos.py`.
