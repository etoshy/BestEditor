# 06 · Textos animados avulsos

São os mesmos estilos dos destaques ([05](05-destaques.md)), usados de dois jeitos:

1. **Aba 🔤 Textos do Estúdio**: qualquer texto, em qualquer estilo, no cursor da timeline. Você escolhe a posição,
   se o fundo do estilo entra e o som. Ele vira um destaque com `avulso: true`, que **mantém o tempo que você
   escolheu** e não é reancorado na fala.
2. **Página `/textos`** (rodapé → 🔤 Textos animados): exporta **só o texto animado** como vídeo, para usar em
   qualquer editor:
   - fundo preto (MP4);
   - fundo verde para chroma key (MP4);
   - **transparente**: MOV ProRes 4444 (Premiere, DaVinci, CapCut PC) ou WEBM VP9 (navegador, OBS);
   - nos formatos 16:9, 9:16 e 1:1.

## Criar um estilo de texto novo

É o mesmo que criar um destaque. Um estilo dos extras aparece **na hora** na aba 🔤 Textos e na página `/textos`:

```json
{"destaques": {"meu_titulo_rosa": {"base": "trailer", "label": "Título rosa", "categoria": "meus",
  "tipografia": {"fonte": "abril"}, "coreografia": {"entrada": "pop"}}}}
```

Para o texto sair rosa num projeto, use a paleta do projeto, ou a cor própria do destaque no painel
✍ Texto, ênfase e animação.

## Pela IA

No prompt de edição, a IA pode mandar `"avulso": true` com `start`/`end` próprios. É útil para um título que não é
falado.

## Com código

- `dp_destaques.renderizar_avulso()` faz o vídeo da página `/textos`.
- `FUNDOS_AVULSO` lista os formatos de saída. Para um formato novo (outra cor de chroma, outro codec), inclua a
  saída ali e trate o caso em `renderizar_avulso`.
