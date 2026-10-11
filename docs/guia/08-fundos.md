# 08 · Fundos dos destaques e das cenas

## Fundos dos destaques (`dp_fundos.FUNDOS_DESTAQUE`)

É o que aparece **atrás do texto** de um destaque. Clique no destaque → **🖼 Fundo e cor**, ou aba 💬 Destaques →
**🖼 Fundo dos destaques**, que vale como padrão do projeto. Cada fundo tem **cor** e **intensidade** (0,15–1).

| Grupo | Ids |
|---|---|
| Simples | `nenhum`, `escurecer`, `vinheta`, `gradiente`, `painel`, `flash`, `veu_lateral`, `espaco_negativo` |
| Tratamento da imagem | `pb`, `granulado`, `crt`, `filme_queimado`, `nevoa`, `luz` |
| Imagem desfocada | `desfoque`, `desfoque_escuro`, `desfoque_cor` |
| Linhas e grades | `faixas`, `linhas`, `grade`, `ondas`, `grade_ondulada`, `grade_3d`, `pontos`, `mapa` |
| Cor | `banho_cor`, `cor_gradiente`, `cor_solida`, `papel`, `jornal`, `tinta`, `galeria` |

**Num estilo seu** (extras), use o id em `cena.fundo`, com `cena.cor` se quiser:

```json
{"destaques": {"meu_selo": {"base": "selo_ano", "cena": {"fundo": "papel"}}}}
```

Em fundo claro (papel, cor clara), o texto fica escuro sozinho.

### Fundo novo (código)

1. Inclua a linha em `FUNDOS_DESTAQUE`: `("meu_fundo", "Nome", "Grupo", usa_cor)`.
2. Faça o desenho:
   - **imagem**: em `padrao_png(tipo, …)`, desenhe o PNG RGBA com PIL e inclua o id na lista do fim de
     `etapas_destaque()` (a que devolve `padrao_png`);
   - **filtro sobre o vídeo**: devolva as etapas do ffmpeg em `etapas_destaque()`
     (`[base]…:enable='between(t,a,b)'[base]`).
3. Prévia em `templates/estudio.html → cssFundo()`, com o CSS equivalente (gradientes, `repeating-linear-gradient`…).
   A telinha e o vídeo precisam bater: `escurecer_igual_previa()` mostra como converter "camada preta com opacidade"
   para o ffmpeg.
4. A miniatura da grade 🖼 Fundo é o próprio CSS (não precisa gerar imagem).

## Fundos das cenas (`dp_fundos.FUNDOS_CENA`)

É o que aparece **atrás das janelas** de uma cena ou take:

- vidro (a própria mídia desfocada), vidro com cor, mídia escurecida;
- escuro com grão, concreto, papel, película, borda queimada, marcas de registro, cantoneiras;
- clarão, luz, gradiente e cor sólida;
- linhas, grade, ondas, grade ondulada, grade 3D e pontos.

Na cena dos extras, `"fundos": ["escuro", "papel"]` decide as opções e a ordem (o 1º é o padrão).

Fundo de cena novo (código):

1. Inclua a linha em `FUNDOS_CENA`.
2. Desenhe em `cenas_dp.gerar_fundo(estilo, …)`.
3. Faça o CSS em `cenas_dp._css_fundo()` (prévia e galeria) e em `cssFundo()` do Estúdio.
