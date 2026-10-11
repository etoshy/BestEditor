# 02 · Efeitos de câmera e de atmosfera (overlays)

Os efeitos ficam por **trecho**: painel do trecho → Efeito, ou aba **Efeitos**. Há duas famílias:

| Família | O que faz | Só em foto? | Onde é feito |
|---|---|---|---|
| **Câmera** (movimento) | zoom in/out, pan, zoom rápido, zoom com giro, zoom "respirando", zoom + pan | sim (Ken Burns) | `video_assembler._render_image_with_ken_burns` |
| **Atmosfera** (os "overlays") | luz vazando, poeira, neblina, scanlines, bokeh, véu dourado, partículas, aberração cromática, tremulação… | não | `dp_visual.atmosfera()` |

Na **Direção**, o eixo "Overlays" são os efeitos de atmosfera: eles entram nos trechos que não têm movimento.

Lista com ids: `python dp_guia.py listar efeitos`.

## Sem programar

```json
{
  "efeitos": [
    {"id": "zoom_lento_foto", "rotulo": "Zoom lento (foto)", "camera": "in"},

    {"id": "calor_suave", "rotulo": "Calor suave", "familia": "atmosfera", "int": 1, "energia": 0.3,
     "filtro": "[base]eq=gamma=1.06:saturation=1.12,colorbalance=rm=0.05:bm=-0.04[base]"},

    {"id": "poeira_dourada", "rotulo": "Poeira dourada", "igual_a": "ov_poeira"}
  ]
}
```

Diga **um** destes:

- `camera`: um dos movimentos do montador. A câmera só vale em **foto**: num vídeo o site ignora, e a IA também é
  avisada disso.
  - `in`, `out`
  - `pan_left`, `pan_right`, `pan_up`, `pan_down`
  - `rapido`, `giro`, `respiro`
  - `zoom_pan_left`, `zoom_pan_right`, `zoom_pan_up`
  - `static`
- `filtro`: filtros do ffmpeg aplicados no trecho. Precisa **começar com `[base]` e terminar com `[base]`**. Dentro,
  separe os filtros por vírgula.
- `igual_a`: outro efeito (`ov_poeira`, `ov_leak`, `zoom_respiro`…), com outro nome.

### Ideias de `filtro` (todos testados no ffmpeg)

```text
brilho que pulsa              [base]eq=brightness='0.04*sin(2*PI*t/1.5)':eval=frame[base]
tremor de câmera leve         [base]scale=iw+24:ih+24,crop=iw-24:ih-24:'12+8*sin(t*13)':'12+8*cos(t*11)'[base]
grão forte                    [base]noise=alls=22:allf=t+u[base]
vinheta respirando            [base]vignette=angle='PI/4+0.1*sin(t)':eval=frame[base]
cores deslocadas (glitch)     [base]rgbashift=rh=6:bv=-4[base]
preto e branco contrastado    [base]hue=s=0,eq=contrast=1.3[base]
```

Use `t` (o tempo em segundos dentro do trecho) para animar. Se o filtro muda o tamanho do quadro, ele precisa
terminar **exatamente** no tamanho original, como no tremor: aumenta 24 px com `scale` e corta 24 px com `crop`.

Depois: `python dp_guia.py miniaturas` gera a prévia em `galeria/overlays/<id>.mp4` (atmosfera) ou
`galeria/animacoes/camera_<id>.mp4` (câmera).

## Com código

**Atmosfera com textura** (partículas, luz desenhada…). Em `dp_visual.py`:

1. Em `_png_textura(tipo, …)`, desenhe a textura num PNG RGBA (PIL/numpy). Pode ser maior que a tela, para poder
   andar.
2. Em `atmosfera()`:
   - ponha o efeito no dicionário `tex` (`"meu_id": "minha_textura"`);
   - ponha o movimento no dicionário `pos` (expressões de `x`/`y` com `t`).
3. Rótulo em `_ROT_EFEITO` e entrada em `darkplanner.json → catalogs.effects` (`id`, `familia`, `int`, `energia`;
   `precisaImagem: true` só para câmera).

**Movimento de câmera novo** (por exemplo "zoom em espiral"):

1. Em `video_assembler.py`:
   - inclua o nome em `_ZOOM_DIRECTIONS_VALIDAS`;
   - escreva a expressão do `zoompan` dentro de `_render_image_with_ken_burns`, ao lado de `rapido`/`giro`/`respiro`.
2. Em `dp_visual.EFEITO_PARA_ZOOM`, `"meu_efeito": "espiral"`.
3. Prévia: em `estudio.html → kenBurns()`, acrescente a transformação CSS do movimento.

Prévia no monitor: os efeitos de atmosfera **não** aparecem no monitor, só na montagem e na miniatura da galeria
(passe o mouse). A câmera aparece aproximada.
