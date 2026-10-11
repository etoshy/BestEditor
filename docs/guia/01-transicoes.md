# 01 · Transições

A transição é o que acontece na **emenda** entre dois trechos (o losango da timeline). O valor guardado em cada
trecho pode ser de três tipos:

| Tipo | Exemplo | De onde vem |
|---|---|---|
| Nativa do ffmpeg | `fade`, `wipeleft`, `circleopen`, `pixelize` | o filtro `xfade` (58 nativas) |
| Nossa | `blinds_h`, `pinwheel`, `dp_shutter_foco` | `video_assembler.TRANSICOES_CUSTOMIZADAS` e `cenas_dp.TRANSICOES_SHUTTER` |
| Do DarkPlanner | `dp:ft_pk_leak3`, `dp:gl_oss_heart` | `darkplanner.json → catalogs.transitions`, que vira nativa ou fórmula em `dp_visual.MAPA_TRANSICOES` |

Para ver todas: `python dp_guia.py listar transicoes`.

## Sem programar: arquivo de extras

```json
{
  "transicoes": [
    {"id": "cortina_central", "rotulo": "Cortina fechando no centro", "familia": "varredura",
     "int": 2, "energia": 0.5, "ritmo": "medio", "xfade": "horzclose"},

    {"id": "varredura_diagonal_suave", "rotulo": "Varredura diagonal suave", "familia": "varredura",
     "expr": "if(lt((X/W+Y/H)/2+0.05*sin(Y/H*18),P*1.1),B,A)"},

    {"id": "luz_dourada_2", "rotulo": "Luz dourada (cópia)", "familia": "luz", "igual_a": "ft_pk_leak3"}
  ]
}
```

- `id`: só minúsculas, números e `_`. No site a transição vira `dp:<id>`, por exemplo `dp:cortina_central`.
- `rotulo`: o nome na galeria. O emoji vem da família.
- `familia`: decide o **som automático** e o emoji:
  - `fade` 🌗
  - `luz` 💡
  - `varredura` 🧹
  - `forma` 🔷
  - `impacto` 💥
  - `glitch` 📺
  - `combo` 🎬
  - `splash` 💦
  - `corte` ✂️
- `int` (1–5), `energia` (0–1) e `ritmo` (`rapido` | `medio` | `cinema`): usados pela Direção e pela IA para
  combinar a transição com o clima do vídeo.
- Diga **um** destes três:
  - `xfade`: nome de uma nativa ou de uma "nossa" (a lista sai em `python dp_guia.py listar transicoes`).
  - `expr`: uma fórmula por pixel (explicada logo abaixo).
  - `igual_a`: outra transição (`ft_pk_leak3` ou `dp:ft_pk_leak3`), com outro nome, família e som.

Depois de salvar: rode `python dp_guia.py verificar` e **reinicie o site**.

### A fórmula `expr`

O ffmpeg calcula a fórmula **para cada pixel de cada quadro**, e o resultado é a cor desse pixel. Variáveis
disponíveis:

| Variável | O que é |
|---|---|
| `P` | o progresso: **0 = só o trecho A** (o que sai) até **1 = só o B** (o que entra). O site já converte para o sentido do ffmpeg |
| `X`, `Y` | a posição do pixel |
| `W`, `H` | a largura e a altura do quadro |
| `A`, `B` | o valor do pixel no trecho A e no trecho B |
| `PLANE` | o plano de cor (o vídeo é YUV): `0` = brilho (Y), `1` e `2` = cor (U, V) |

Receitas:

```text
varre da esquerda pra direita         if(lt(X/W,P),B,A)
abre do centro (círculo)              if(lt(hypot(X-W/2,Y-H/2),P*hypot(W/2,H/2)),B,A)
dissolve comum                        A*(1-P)+B*P
persianas de 40 px                    if(lt(mod(Y,40)/40,P),B,A)
borda ondulada                        if(lt(X/W+0.06*sin(Y/H*20),P*1.12-0.06),B,A)
passa por branco no meio              clip((A*(1-P)+B*P)*(1-max(0,1-abs(2*P-1)*1.4))+if(eq(PLANE,0),235,128)*max(0,1-abs(2*P-1)*1.4),0,255)
```

Cor sólida em YUV: branco é `if(eq(PLANE,0),235,128)` e preto é `if(eq(PLANE,0),16,128)`.

Para testar a fórmula antes, sem abrir o site:

```bash
ffmpeg -f lavfi -i color=red:s=640x360:d=2 -f lavfi -i color=blue:s=640x360:d=2 \
  -filter_complex "[0][1]xfade=transition=custom:duration=1:offset=1:expr='if(lt(X/W,1-P),B,A)'" teste.mp4
```

No teste direto, troque `P` por `1-P`, porque o ffmpeg conta ao contrário. No arquivo de extras, escreva
normalmente com `P`.

> Dentro do JSON, aspas viram `\"` e a vírgula da fórmula fica como está (o site já escapa para o ffmpeg).

## Prévia no Estúdio

- Uma transição `xfade` (ou `igual_a` de uma nativa) mostra no monitor a prévia da nativa: varre, abre em círculo,
  desliza…
- Uma `expr` aparece como **fade** na prévia. Para ver de verdade, monte o vídeo ou passe o mouse na galeria.

## Som automático

Cada transição ganha um som pela família (`dp_sons._TR_FAMILIA`). Para fixar um som específico numa transição sua,
há duas opções:

- no Estúdio: clique no losango → som da transição;
- no código: em `dp_sons._TR_ESPECIFICO`, `"dp:cortina_central": "transicoes/whoosh"`.

## Com código (visual totalmente novo)

1. **Fórmula reaproveitável** (luz vazando, queimado, splash…): em `dp_visual.py` existem os geradores `_leak()`,
   `_burn()`, `_splash()`, `_glitch()` e `_blocos()`. Crie a fórmula em `_ESPECIAIS["minha"] = …` e aponte no
   `_MAPA_TR`: `meu_id:@minha`. Inclua a entrada em `darkplanner.json → catalogs.transitions` (`id`, `familia`,
   `int`, `energia`, `ritmo`).
2. **Transição "nossa" com nome próprio**, sem o prefixo `dp:`:
   - acrescente em `video_assembler.TRANSICOES_CUSTOMIZADAS` (a mesma convenção, P de 0 a 1);
   - acrescente o rótulo em `site_config.TRANSITION_LABELS`.
3. **Prévia**: em `templates/estudio.html → efeitoTransicao()`, acrescente um `else if` com `clipPath`/`transform`
   para ela. Sem isso a prévia é um fade.
4. Rode os testes (`pytest test_video_assembler.py test_v75_efeitos.py`) e monte um vídeo curto para conferir.
