# 03 · Entradas e saídas dos trechos

A **entrada** é o gesto no começo do trecho, a **saída** é o gesto no fim. Exemplos: pop, punch in, giro, TV
ligando, onda de choque, mola, estilingue, virada 3D, fumaça, assenta, revela…

- Painel do trecho → Entrada / Saída, ou aba **🖼️ Biblioteca → Animações**: clique aplica a entrada,
  **Shift+clique** aplica a saída.
- As mesmas ids valem para entrada e saída. A saída é o gesto ao contrário.
- **A saída só aparece quando a emenda seguinte é corte seco.** Com transição, a transição manda.
- O tamanho do gesto vem do `durAlvoS`, limitado a 0,2–1,2 s e a 35% da duração do trecho.

Lista: `python dp_guia.py listar entradas`.

## Sem programar: outro nome e outra duração

```json
{
  "entradas": [
    {"id": "pop_rapido", "rotulo": "Pop rápido", "igual_a": "pop", "durAlvoS": 0.25},
    {"id": "ergue_lento", "rotulo": "Ergue lento", "igual_a": "ergue_suave", "durAlvoS": 1.0}
  ]
}
```

- `igual_a`: o gesto existente em que ela se baseia. É obrigatório.
- `durAlvoS`: a duração natural do gesto, em segundos.
- `familia`, `int` e `energia` (opcionais): usados pela Direção e pela IA.

Depois: `python dp_guia.py miniaturas` gera `galeria/animacoes/entrada_<id>.mp4`.

## Com código: gesto novo

Em `dp_visual._gesto(gid, p, W, H)` cada gesto devolve **expressões em função de `p`**. `p` vai de 0 (começo do
gesto) a 1 (assentado); `e` é a versão suavizada (ease-out) e `inv` = 1 − e.

| Campo | O que faz | Exemplo |
|---|---|---|
| `s` | escala | `f"(0.6+0.4*{e})"` (cresce de 60% a 100%) |
| `sx`, `sy` | escala só na horizontal/vertical | `f"max(0.02,abs(cos({inv}*PI/2)))"` (virada 3D) |
| `dx`, `dy` | deslocamento em px | `f"({H * 0.08:.0f}*{inv})"` (vem de baixo) |
| `r` | rotação em radianos | `f"(2*PI*{inv})"` (giro) |
| `fade` | "1" = aparece com fade | — |
| `flash` | clarão branco no começo (0–1) | `"0.35"` |
| `blur` | "1" = começa desfocado | — |
| `lag` | "1" = rastro (ghost trail) | — |

Passos:

1. Escreva o `elif gid == "meu_gesto":` em `_gesto()`.
2. Rótulo em `_ROT_ENTRADA` e item em `darkplanner.json → catalogs.entrances` (`id`, `durAlvoS`, `familia`, `int`,
   `energia`).
3. **Prévia**: em `estudio.html → gestoCss()`, acrescente a transformação CSS. Sem isso, a prévia mostra só um fade.
4. `python dp_guia.py miniaturas` e `pytest test_v75_efeitos.py test_dp_completo.py`.

## Entradas das cenas e dos destaques

São coisas diferentes:

- os **takes** das cenas usam os movimentos de `cenas_dp._MOVIMENTOS` (ver [09](09-cenas-e-takes.md));
- os **destaques de texto** usam as animações de texto (ver [05](05-destaques.md)).
