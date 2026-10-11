# 04 · Filtros de cor

O filtro é a **identidade de cor do vídeo inteiro** (regra do DarkPlanner: **um filtro por vídeo**). Ele fica na aba
**🎨 Direção** ou na **🖼️ Biblioteca → Filtros**, que mostra a mesma foto com cada filtro. São 74 de fábrica.

Lista: `python dp_guia.py listar filtros`.

## Sem programar

```json
{
  "filtros": [
    {"id": "noite_azul", "rotulo": "Noite azul", "grupo": "meus",
     "cadeia": "colorbalance=bs=0.18:bm=0.1:rh=-0.04,eq=brightness=-0.06:saturation=0.85,vignette=angle=PI/5",
     "css": "saturate(.85) brightness(.94) hue-rotate(12deg)"}
  ]
}
```

- `cadeia`: os filtros do ffmpeg (o mesmo que iria em `-vf`), separados por vírgula. Ou use `igual_a` para copiar a
  cadeia de outro.
- `css`: a **prévia** no monitor do Estúdio, com filtros CSS (`grayscale()`, `sepia()`, `saturate()`, `contrast()`,
  `brightness()`, `hue-rotate()`, `blur()`, `invert()`). Sem `css`, a prévia usa um contraste leve genérico.
- `grupo`: só organiza a galeria.

Depois: `python dp_guia.py miniaturas` gera `galeria/filtros/<id>.jpg`.

### Peças do ffmpeg que mais ajudam

| Filtro | Para quê | Exemplo |
|---|---|---|
| `eq` | brilho, contraste, saturação, gama | `eq=contrast=1.2:saturation=1.1:brightness=0.03:gamma=1.05` |
| `colorbalance` | puxar sombras (s), meios (m) e altas (h) para uma cor | `colorbalance=rs=-0.1:bs=0.15:rh=0.12:bh=-0.1` (teal & orange) |
| `curves` | curvas (ou presets: `vintage`, `cross_process`, `lighter`…) | `curves=all='0/0.06 0.5/0.5 1/0.94'` |
| `hue` | matiz e saturação | `hue=h=-10:s=0.8`; preto e branco: `hue=s=0` |
| `colorchannelmixer` | mistura de canais (sépia) | ver o `sepia` em `dp_visual._F` |
| `vignette` | escurecer as bordas | `vignette=angle=PI/5` |
| `noise` | grão | `noise=alls=10:allf=t` |
| `gblur` | suavizar | `gblur=sigma=0.6` |
| `lut3d` | um LUT `.cube` | `lut3d=file=assets/luts/meu.cube` (o caminho precisa existir no PC) |

Teste rápido numa foto: `ffmpeg -i foto.jpg -vf "SUA_CADEIA" saida.jpg`.

## Com código

1. Em `dp_visual._F`: `"meu_id": ("Rótulo", "cadeia")`.
2. Em `darkplanner.json → catalogs.filters`: `{"id": "meu_id", "group": "meus"}`.
3. Prévia em `estudio.html → cssDoFiltro()` (o mapa `m`).
4. `python dp_guia.py miniaturas`.
