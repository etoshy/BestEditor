# 05 · Destaques de texto (os estilos do DarkPlanner)

Os destaques são os textos que aparecem **por cima do vídeo no tempo da fala**: manchetes, selos de ano, número,
porcentagem e dinheiro, citações, lower thirds, capítulos, marca-texto, carimbo, digitação, contador… São 207 de
fábrica, em `darkplanner.json → highlights`.

- Aba **💬 Destaques** do Estúdio, faixa "Destaques" da timeline e "✨ Sugerir automaticamente".
- A IA também cria destaques pelo prompt de edição.
- Na montagem, cada destaque vira uma **legenda ASS animada** (libass, com as fontes de `assets/fonts/dp`) mais o
  **tratamento da cena** atrás do texto (escurecer, grade, desfoque…).

Lista: `python dp_guia.py listar destaques`.

## Sem programar: copie um estilo e mude o que quiser

```json
{
  "destaques": {
    "titulo_neon_grade": {
      "base": "epico",
      "label": "Título neon com grade",
      "categoria": "meus",
      "amostra": "A NOITE QUE MUDOU TUDO",
      "tipografia": {"fonte": "bebas", "caixaAlta": true, "italico": false},
      "coreografia": {"entrada": "glitch", "saida": "blur"},
      "cena": {"tratamento": "front_grid", "fundo": "grade_3d", "cor": "#2F7BFF"},
      "whenToUse": ["Abertura de capítulo com clima tecnológico/noturno"],
      "maxPorVideo": 2
    }
  }
}
```

- A chave (`titulo_neon_grade`) é o id: minúsculas, números e `_`.
- `base`: o estilo copiado. Tudo o que você não escrever vem dele. Os sub-objetos (`tipografia`, `coreografia`,
  `cena`…) são **mesclados**: você muda só o campo que escreveu. Sem `base`, o ponto de partida é o `minimal`.
- `categoria: "meus"` cria a prateleira **⭐ Meus estilos** na galeria.
- Depois: `python dp_guia.py miniaturas` gera `galeria/destaques/<id>.jpg`. A prévia animada (quando você passa o
  mouse) é gerada na hora.

### Os campos que mudam o visual

| Campo | Valores | Efeito |
|---|---|---|
| `forma` | `centro_titulo`, `centro_frase`, `palavra`, `marca`, `terco`, `selo_canto`, `cartao_dado`, `citacao`, `cascata`, `digitacao`, `sublinhado`, `slab`, `painel_meio`, `carimbo`, `doc` | o **desenho**: tamanho da letra, caixa colorida (`selo_canto`, `cartao_dado`, `slab`, `marca`), barra lateral (`terco`, `doc`), aspas (`citacao`)… |
| `zona` | `centro`, `terco_inf`, `terco_sup`, `canto_bl`, `canto_tl`, `canto_tr`, `canto_br`, `esq`, `dir`, `painel_esq`, `painel_dir`, `baixo`, `alto`, `inline`, `full_bleed`, `metade` | onde fica na tela |
| `tipografia.fonte` | `anton`, `bebas`, `oswald`, `teko`, `cinzel`, `playfair`, `garamond`, `abril`, `alfaslab`, `montserrat`, `poppins`, `archivo`, `worksans`, `merriweather`, `lora`, `mono`, `specialelite`, `rajdhani`, `fjalla`, `staatliches`, `robotocond`, `barlowcond` (e as suas, ver [12](12-fontes.md)) | a fonte |
| `tipografia.caixaAlta` / `italico` | `true`/`false` | maiúsculas / itálico |
| `coreografia.entrada` | `fade`, `pop`, `punch`, `blur`, `slide`, `letras`, `type`, `cascata`, `glitch`, `flip`, `tracking`, `revelar`, `cortina`, `stamp`, `acende`, `marca`, `cruzado`, `mira`, `linha_tempo`, `versus`, `matchcut`, `grade`, `pino`, `assenta`, `contador` | a animação de entrada do texto |
| `coreografia.saida` | `fade`, `blur`, `zoom`, `slide`, `wipe`, `riscar` | a saída |
| `coreografia.interna` | `brilho`, `flutua` ou `null` | movimento enquanto está na tela |
| `coreografia.porBatida` + `timing.modo: "porBatida"` | `true` | cada palavra entra no tempo em que é falada |
| `coreografia.ritmo` (ou `ritmo`) | `rapido`, `medio`, `cinema` | o tempo de entrada e saída e quanto ele respira (`rules.timing.classes`) |
| `cena.tratamento` | `dim`, `vignette`, `gradient`, `blur`, `flash`, `panel`, `front_grid`, `fullscreen_grid`, `color_wash`, `side_veil`, `haze`, `light`, `archive`, `map`, `none`… | o que acontece com o vídeo atrás do texto |
| `cena.fundo` (+ `cena.cor`) | um id de [08 · Fundos](08-fundos.md) (`grade_3d`, `faixas`, `papel`, `cor_solida`…) | o fundo desenhado atrás (sobrepõe o tratamento) |
| `audio.assets` | ids de som (`impacto/impacto_5`, um som seu…) — ver [11](11-sons.md) | o som do destaque |
| `audio.evento` | `assentamento` (o pico no impacto), `porBatida` (um por palavra), `tipagem`, `cama`, `rolagem`, `entrada` (acompanham desde o início), `nenhum` | quando o som toca |

### Os campos que decidem **quando** ele é usado (motor automático e IA)

| Campo | O que faz |
|---|---|
| `papel` | `abertura`, `secao`, `destaque`, `enfase`, `info`, `apoio`, `conclusao` — o "orçamento" do motor é por papel |
| `subtipos` | `ano`, `data`, `hora`, `numero`, `pct`, `dinheiro`, `nome`, `rotulo`, `local`, `contagem`, `artigo`, `biblia`, `titulo`, `frase`, `pergunta`, `impacto`, `forte`, `citacao`, `capitulo`, `corte` — o "✨ Sugerir" usa esse estilo quando acha esse tipo de coisa na fala (`null` = qualquer) |
| `exclusivo` / `subtiposProibidos` | só com aqueles subtipos / nunca com eles |
| `palavras` | `[mín, máx]` palavras do texto |
| `maxPorVideo` | limite por vídeo |
| `autoEligible` / `manualOnly` | o motor e a IA podem escolher / só você, à mão |
| `whenToUse` / `whenNotToUse` | listas de frases. A **1ª frase** vai para a IA e aparece na dica da galeria |
| `amostra` | o texto da miniatura |

## Com código: forma nova

O desenho é feito em `dp_destaques.py`:

- `medidas_texto()`: tamanho, quebra e posição. Ele usa `_TAMANHO[forma]` e `HL_POS_PREVIA[zona]`.
- `_eventos_de_um()`: os eventos ASS (texto, caixa, barra, aspas, animações).
- `_anim()` e `ANIMS_ENTRADA`: as famílias de animação. Uma família nova precisa:
  - entrar em `ANIMS_ENTRADA`;
  - ganhar o seu bloco em `_eventos_de_um`;
  - ganhar o seu sabor por palavra em `_tag_palavra`.
- `filtros_de_tratamento()`: o tratamento da cena.

E a prévia em `templates/estudio.html → desenharUmHl()` (com `HL_TAM`, `HL_POS`): a forma nova precisa do mesmo
tamanho e lugar lá. Os testes `test_estudio.py` e `test_dp_completo.py` comparam a telinha com o vídeo.
