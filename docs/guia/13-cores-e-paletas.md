# 13 · Cores e paletas

A **paleta do projeto** tem três cores: primária, secundária e acento. A primária gera os tons claro, vivo, médio e
escuro. Fica na aba 🎨 Direção → **🎨 Cores do projeto**.

Modos:

- **Paleta do projeto**: tom sobre tom, e tudo o que é adaptativo veste a paleta.
- **Automático**: cada estilo com as cores dele.

Escolha onde a paleta vale:

- cenas (rótulos, VS, aspas, linhas, fundos coloridos, clarão);
- destaques e textos;
- legendas;
- transições de luz (leaks, burns, brilho).

**Cor neutra** (cinza, branco, preto) nunca é trocada.

## Sem programar

- **Pelo Estúdio**: monte a paleta e clique em **💾 Salvar como minha paleta**. Ela fica em
  `predefinicoes_usuario.json` e vale para todos os projetos.
- **Pelos extras** (bom para levar para outro PC ou para o GitHub):

```json
{"paletas": [{"id": "minha_marca", "nome": "Minha marca", "primaria": "#00C2A8", "secundaria": "#B8FFF4", "acento": "#FF5470"}]}
```

A IA também pode mandar `"paleta"` no JSON.

## Com código

- `dp_cores.PALETAS`: as paletas prontas.
- `tons_da_paleta()` e `derivar()`: como os tons e a secundária/acento saem da primária.
- `ESCOPOS`: onde a paleta pode valer. Um escopo novo precisa ser respeitado em quem desenha, via
  `dp_cores.vale_para(paleta, "escopo")`.
