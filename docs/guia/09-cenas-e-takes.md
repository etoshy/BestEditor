# 09 · Cenas e takes (templates com janelas)

Uma **cena** põe a mídia do trecho dentro de uma composição: moldura, retrato com texto, lado a lado, tríade,
mosaico, frente & fundo, citação, ficha… Estão na aba **🎬 Cenas** do Estúdio e na faixa "Cenas" da timeline. São
149 de fábrica, em `assets/darkplanner/cenas_catalogo.json`.

**Regra dos slots.** Um template de N slots aplicado no trecho X cobre X e os N−1 trechos seguintes:

- cada mídia vira um **take** que entra no tempo da própria fala;
- os takes anteriores continuam na tela;
- as emendas dentro da cena não têm transição.

Listas: `python dp_guia.py listar cenas` e `python dp_guia.py listar arranjos`.

## Sem programar

```json
{
  "cenas": {
    "MEU_TRIO_COLUNAS": {
      "nome": "Meu trio em colunas",
      "janelas": [[0.03, 0.08, 0.30, 0.70], [0.35, 0.08, 0.30, 0.70], [0.67, 0.08, 0.30, 0.70]],
      "texto": [0.06, 0.82, 0.88, 0.14],
      "fundos": ["escuro", "papel"],
      "motion": ["ergue_suave", "assenta", "revela_cima"],
      "whenToUse": ["Três fotos do mesmo assunto lado a lado"],
      "autoEligible": false, "manualOnly": true
    },
    "MEU_PAR_PAPEL": {"base": "MULTITAKE_06", "nome": "Par em papel de arquivo", "fundo_fixo": "papel"}
  }
}
```

O id aceita maiúsculas (como os de fábrica). Use **um** destes três caminhos:

| Caminho | Como |
|---|---|
| `base` | copia outro template (nome, slots, textos, fundos, movimentos e o arranjo de janelas) e você muda o que quiser |
| `arranjo` | usa um arranjo pronto: `tela_cheia`, `moldura`, `moldura_larga`, `retrato_dir`, `retrato_esq`, `barra_esq`, `barra_dir`, `citacao`, `nome`, `cartao`, `lado_a_lado`, `diagonal`, `sobreposicao`, `confronto`, `antes_depois`, `ff_dir`, `ff_esq`, `ff_zoom`, `ff_vertical`, `painel_dir`, `painel_esq`, `triade`, `cascata`, `leque`, `escada`, `pilha`, `linha_tempo`, `mosaico`, `sequencia4` |
| `janelas` | as suas janelas: uma por take, cada uma `[x, y, largura, altura]` em **fração da tela** (0 a 1, a partir do canto de cima à esquerda). O número de janelas vira o número de slots |

Outros campos:

- `texto`: `[x, y, largura, altura]` da área do texto (a fala ou os campos).
- `fundos`: os fundos que a cena oferece (ver [08](08-fundos.md)); o 1º é o padrão. Ou `fundo_fixo`, que fica
  sempre.
- `motion`: o movimento de entrada de cada take, em rodízio:
  - `assenta`, `soft_land`, `desliza_suave`, `ergue_suave`;
  - `revela_cima`, `revela_esq`, `revela_diag`;
  - `slide_left`, `slide_right`, `fade`, `dissolve_foco`, `zoom_soft`;
  - `queda`, `trilho`, `sobe`.

  Ou `movimento` para um só, igual em todos.
- Efeitos da cena: `foco` (a janela foca), `flash` (clarão na entrada), `escurecer` (0–1).
- `textFields`: os campos de texto. Os de `source: "speech"` mostram **a fala** do take e escondem a legenda ali.
  Os de `source: "fixed"` são campos que você ou a IA preenchem ("TÓPICO", "CAPÍTULO"…).
- `durMinS`, `durIdealS`, `durMaxS`, `autoEligible`, `manualOnly`, `whenToUse`, `whenNotToUse`: as regras para a IA.
  Deixe `autoEligible: false` enquanto estiver testando.

No vídeo **vertical (9:16)**, as janelas se reorganizam sozinhas: lado a lado vira um em cima do outro, e o texto
vai para a faixa de baixo.

## Com código

- Um **arranjo novo** com nome:
  1. Inclua em `cenas_dp._ARRANJOS` (`janelas`, `texto`, e opcionais: `rotulo`, `aspas`, `borda`, `linha`,
     `fundo_take0`, `revela_ultimo`…).
  2. Ligue o template a ele em `_MAPA`.
- Um **efeito de composição novo**: em `renderizar_cena()`.
- **Prévia**: o Estúdio desenha as janelas pelo `catalogo_para_editor()`, então funciona sozinho. Efeitos especiais
  precisam de código em `desenharCenaMonitor()`.
- Teste com `pytest test_cenas_dp.py`. Ele renderiza todos os arranjos.
