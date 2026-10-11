# 17 · Ferramentas, testes e o checklist de código

## `python dp_guia.py` (rode na pasta do site)

| Comando | O que faz |
|---|---|
| `verificar` | confere os extras: JSON quebrado, seção desconhecida, id repetido, `base`/`igual_a` que não existe, `xfade` que não é nativa, `filtro` sem `[base]`, fonte ou som que não existe. Também confere o catálogo todo: filtro sem cadeia, transição sem mapeamento, miniatura faltando |
| `miniaturas [--refazer id …]` | gera **só** as miniaturas e prévias que faltam (`--refazer` apaga antes as de um item que você mudou) |
| `listar <tipo>` | ids para usar em `base`/`igual_a`. Tipos: `transicoes`, `efeitos`, `entradas`, `filtros`, `destaques`, `cenas`, `arranjos`, `fundos`, `fontes`, `sons`, `paletas` |
| `som <arquivo> --categoria x --nome "Y"` | converte, mede o pico e registra um som |
| `fonte <arquivo.ttf> --chave x --nome "Y"` | renomeia a família para "DP Y" e registra a fonte |

A página **📘 Guia** do site mostra os mesmos erros dos extras e tem o botão **🔄 Reler os extras** (sem reiniciar,
menos para transição nova).

## Fluxo para criar com extras

```text
copiar exemplo → mudar → python dp_guia.py verificar → python dp_guia.py miniaturas → reiniciar o site → testar no Estúdio → montar um vídeo curto
```

Os exemplos prontos estão em `docs/guia/exemplos/`: transições, efeitos, entradas, filtros, destaques, cenas e
paletas. Copie para `assets/darkplanner/extras/` e mude.

## Checklist quando for mexer no código

1. **Os dois lados.** Cada visual existe duas vezes:
   - o ffmpeg (`dp_*.py`), que faz o vídeo;
   - o navegador (`templates/estudio.html`), que faz a prévia.

   Mude os dois, ou a telinha mente.
2. **O catálogo.** O item novo precisa estar no catálogo (`darkplanner.json`, `cenas_catalogo.json` ou as listas no
   topo do `dp_*.py`). É de lá que saem as galerias, o prompt da IA (`prompt_edicao.py`) e as Direções.
3. **A IA.** A IA lê o catálogo, e o que ela manda é validado por `prompt_edicao.py` (id que não existe é
   ignorado). Item novo no catálogo já vale para ela.
4. **As miniaturas**: `python dp_guia.py miniaturas`.
5. **Os testes.** Rode os do assunto e, antes de subir para o GitHub, a suíte toda:
   ```bash
   pytest -q test_v84_guia_extras.py test_v75_efeitos.py test_dp_completo.py test_cenas_dp.py
   pytest -q            # tudo (~17 min)
   ```
6. **Um vídeo de verdade**: monte um vídeo curto com o item novo e compare com o monitor. O
   🩺 Diagnóstico pós-export ajuda.

## Onde está cada coisa (resumo)

| Quero criar… | Sem código | Código (ffmpeg) | Prévia (estudio.html) |
|---|---|---|---|
| Transição | `transicoes` | `dp_visual._MAPA_TR` / `_ESPECIAIS`, `video_assembler.TRANSICOES_CUSTOMIZADAS` | `efeitoTransicao()` |
| Efeito de câmera | `efeitos.camera` | `video_assembler._render_image_with_ken_burns` | `kenBurns()` |
| Atmosfera/overlay | `efeitos.filtro` | `dp_visual.atmosfera()` / `_png_textura()` | (só galeria) |
| Entrada/saída | `entradas.igual_a` | `dp_visual._gesto()` | `gestoCss()` |
| Filtro | `filtros` | `dp_visual._F` | `cssDoFiltro()` |
| Destaque | `destaques` | `dp_destaques._eventos_de_um()` | `desenharUmHl()` |
| Legenda | — | `dp_legendas.gerar_ass()` | `desenharLegenda()`, `amostraLeg()` |
| Fundo | (usar) | `dp_fundos.padrao_png()` / `etapas_destaque()` | `cssFundo()` |
| Cena | `cenas` | `cenas_dp._ARRANJOS`, `renderizar_cena()` | `desenharCenaMonitor()` |
| Gráfico | — | `dp_graficos.desenhar()` | (é o próprio PNG) |
| Som | `dp_guia.py som` | `assets/sons/sons.json` | — |
| Fonte | `dp_guia.py fonte` | `assets/fonts/dp/fontes.json`, `dp_destaques._FONTE` | `/dp-fontes.css` (sozinho) |
| Paleta | `paletas` | `dp_cores.PALETAS` | — |
| Censura | — | `dp_censura.aplicar_video()` | `desenharCzMonitor()` |
| Quadro editorial | (usar no Estúdio) | `dp_editorial.TIPOS` + `_d_<tipo>()` | (é o próprio PNG do servidor) |
